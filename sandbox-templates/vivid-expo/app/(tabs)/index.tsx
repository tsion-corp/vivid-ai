import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

export default function HomeScreen() {
  return (
    <SafeAreaView className="flex-1 bg-background dark:bg-background-dark">
      <View className="flex-1 items-center justify-center px-6">
        <Text className="text-2xl font-semibold text-foreground dark:text-foreground-dark">
          Your app is on its way
        </Text>
        <Text className="mt-2 text-center text-base text-muted dark:text-muted-dark">
          Vivid is building it now. This screen changes as soon as the first files land.
        </Text>
      </View>
    </SafeAreaView>
  );
}
